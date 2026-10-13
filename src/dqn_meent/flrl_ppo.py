"""Checkpointable on-policy PPO, with raw Gaussian actions in likelihood ratios.

The reference profile uses the released FLRL CNN shape and PPO hyperparameters.
This worker-driven PyTorch implementation replaces SB3's synchronous Env loop;
it is an adaptation, not a claim of bitwise SB3 or paper-result reproduction.
"""
from copy import deepcopy

import numpy as np
import torch
from torch import nn


class TransformerFeatures(nn.Module):
    """Self-attention over the stacked Fourier-coefficient frames, in place of the reference CNN.

    Tokens are the coefficients (their recent frames as features), the frames (their
    coefficients as features), or every coefficient of every frame. A coefficient's position
    is a learned embedding or a projection of its Fourier mode (kx, ky, real/imaginary part).
    """

    def __init__(self, coefficients, frames, modes, config):
        super().__init__()
        self.coefficients, self.frames = coefficients, frames
        self.tokens = config.get('transformer_tokens', 'coefficient')
        self.pooling = config.get('transformer_pooling', 'mean')
        self.width = width = config.get('transformer_width', 64)
        self.embed = nn.Linear({'coefficient': frames, 'frame': coefficients, 'coefficient_frame': 1}[self.tokens], width)
        nx, ny = modes
        real = (nx + 1) * (ny + 1)
        index = torch.arange(coefficients)
        local = torch.where(index < real, index, index - real)
        # The released ordering runs from the highest mode down, real parts before imaginary parts.
        self.register_buffer('modes', torch.stack([(nx - local // (ny + 1)) / max(nx, 1), (ny - local % (ny + 1)) / max(ny, 1),
                                                   (index >= real).float()], dim=1))
        learned = config.get('transformer_positions', 'learned') == 'learned'
        located = self.tokens != 'frame'
        self.coefficient_position = nn.Parameter(.02 * torch.randn(coefficients, width)) if located and learned else None
        self.mode_position = nn.Linear(3, width) if located and not learned else None
        self.frame_position = nn.Parameter(.02 * torch.randn(frames, width)) if self.tokens != 'coefficient' else None
        self.summary = nn.Parameter(.02 * torch.randn(1, 1, width)) if self.pooling == 'cls' else None
        layer = nn.TransformerEncoderLayer(width, config.get('transformer_heads', 4),
            config.get('transformer_feedforward', 2) * width, dropout=0., activation='gelu', batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.get('transformer_layers', 2), norm=nn.LayerNorm(width),
                                             enable_nested_tensor=False)

    def forward(self, observations):
        frames = observations.reshape(len(observations), self.frames, self.coefficients)  # the history is frame-major
        position = self.coefficient_position if self.coefficient_position is not None else (
            self.mode_position(self.modes) if self.mode_position is not None else None)
        if self.tokens == 'coefficient':
            tokens = self.embed(frames.transpose(1, 2)) + position
        elif self.tokens == 'frame':
            tokens = self.embed(frames) + self.frame_position
        else:
            tokens = (self.embed(frames.unsqueeze(-1)) + position + self.frame_position[:, None]).flatten(1, 2)
        if self.summary is not None:
            tokens = torch.cat([self.summary.expand(len(tokens), -1, -1), tokens], dim=1)
        encoded = self.encoder(tokens)
        return encoded[:, 0] if self.summary is not None else encoded.mean(dim=1)


class ActorCritic(nn.Module):
    def __init__(self, observation_size, action_size, *, frames=1, cnn=False, transformer=None, modes=None):
        super().__init__()
        self.frames, self.cnn = frames, cnn and transformer is None
        if transformer is not None:
            self.features = TransformerFeatures(observation_size // frames, frames, modes, transformer)
        else:
            self.features = nn.Sequential(nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d((2, 1)),
                nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten()) if cnn else nn.Identity()
        width = self.features.width if transformer is not None else 128 if cnn else observation_size
        def branch(output):
            return nn.Sequential(nn.Linear(width, 128), nn.ReLU(), nn.Linear(128, 128), nn.ReLU(),
                                 nn.Linear(128, 128), nn.ReLU(), nn.Linear(128, output))
        self.actor, self.critic = branch(action_size), branch(1)
        self.log_std = nn.Parameter(torch.zeros(action_size))
        # The attention layers keep PyTorch's own initialization; the reference scheme covers the rest.
        for module in (self.modules() if transformer is None else [*self.actor.modules(), *self.critic.modules()]):
            if isinstance(module, (nn.Linear, nn.Conv2d)):
                nn.init.orthogonal_(module.weight, np.sqrt(2)); nn.init.zeros_(module.bias)
        nn.init.orthogonal_(self.actor[-1].weight, .01)
        nn.init.orthogonal_(self.critic[-1].weight, 1.)

    def forward(self, observations):
        if self.cnn:
            observations = observations.reshape(len(observations), 1, -1, self.frames)
        features = self.features(observations)
        return torch.distributions.Normal(self.actor(features), self.log_std.clamp(-10, 2).exp()), self.critic(features).flatten()


class PPO:
    def __init__(self, observation_size, action_size, seed, config, *, cnn=False, frames=1, modes=None):
        self.config = dict(config)
        self.rng = np.random.default_rng(seed)
        transformer = self.config if self.config.get('policy_network', 'cnn') == 'transformer' else None
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.network = ActorCritic(observation_size, action_size, cnn=cnn, frames=frames, transformer=transformer, modes=modes)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=config.get('ppo_learning_rate', .003), eps=1e-5)
        self.rollout, self.updates = [], 0
        self.gamma, self.lam = config.get('ppo_gamma', .9), config.get('ppo_gae_lambda', .95)
        self.return_value = 0.
        self.reward_count, self.reward_mean, self.reward_m2 = 1e-4, 0., 1e-4
        self.last_loss = 0.

    def sample(self, observation):
        obs = np.asarray(observation, dtype=np.float32)
        with torch.no_grad():
            distribution, value = self.network(torch.tensor(obs[None]))
            action = distribution.mean[0].numpy() + distribution.stddev[0].numpy() * self.rng.normal(size=distribution.mean.shape[-1])
            logp = distribution.log_prob(torch.tensor(action[None], dtype=torch.float32)).sum(-1).item()
        return {"observation": obs, "action": action.astype(np.float32), "logp": logp, "value": value.item(),
                "gaussian_mean": distribution.mean[0].numpy().copy(), "gaussian_std": distribution.stddev[0].numpy().copy()}

    def record(self, sample, reward, next_observation, done, *, normalize_reward=False, time_limit=False):
        if normalize_reward:
            self.return_value = reward + self.gamma * self.return_value
            self.reward_count += 1
            delta = self.return_value - self.reward_mean
            self.reward_mean += delta / self.reward_count
            self.reward_m2 += delta * (self.return_value - self.reward_mean)
            reward = float(np.clip(reward / np.sqrt(self.reward_m2 / self.reward_count + 1e-8), -10, 10))
            if done: self.return_value = 0.
        if done and time_limit:
            # The released reference wraps episodes in Gym TimeLimit. Bootstrap
            # its terminal observation, while GAE still stops at the reset.
            with torch.no_grad():
                _, terminal_value = self.network(torch.tensor(np.asarray(next_observation, dtype=np.float32)[None]))
            reward += self.gamma * terminal_value.item()
        self.rollout.append({**sample, "reward": float(reward), "done": done})
        length = self.config.get('rollout_steps', self.config.get('episode_length', 128))
        # The hybrid's frozen local kernel is trained only after whole episodes.
        if len(self.rollout) < length or self.config.get('complete_rollouts', False) and not done:
            return
        with torch.no_grad():
            _, value = self.network(torch.tensor(np.asarray(next_observation, dtype=np.float32)[None]))
        advantage, advantages = 0., []
        next_value = 0. if done else value.item()
        for row in reversed(self.rollout):
            continuation = 1. - float(row['done'])
            delta = row['reward'] + self.gamma * next_value * continuation - row['value']
            advantage = delta + self.gamma * self.lam * continuation * advantage
            advantages.append(advantage)
            next_value = row['value']
        advantages = np.array(advantages[::-1], dtype=np.float32)
        returns = torch.tensor(advantages + np.array([row['value'] for row in self.rollout], dtype=np.float32))
        adv = torch.tensor((advantages - advantages.mean()) / (advantages.std() + 1e-8))
        observations = torch.tensor(np.stack([row['observation'] for row in self.rollout]))
        actions = torch.tensor(np.stack([row['action'] for row in self.rollout]))
        old_logp = torch.tensor([row['logp'] for row in self.rollout])
        n = len(self.rollout)
        batch = self.config.get('batch_size', max(2, n // 2))
        for _ in range(self.config.get('ppo_n_epochs', 3)):
            permutation = self.rng.permutation(n)
            for start in range(0, n, batch):
                ix = permutation[start:start + batch]
                distribution, values = self.network(observations[ix])
                ratio = (distribution.log_prob(actions[ix]).sum(-1) - old_logp[ix]).exp()
                clip = self.config.get('ppo_clip_range', .4)
                loss = -torch.minimum(ratio * adv[ix], ratio.clamp(1 - clip, 1 + clip) * adv[ix]).mean()
                loss = loss + .1 * ((values - returns[ix]) ** 2).mean() - .01 * distribution.entropy().sum(-1).mean()
                if not torch.isfinite(loss): raise ValueError('Nonfinite PPO loss')
                self.optimizer.zero_grad(); loss.backward()
                nn.utils.clip_grad_norm_(self.network.parameters(), .5)
                self.optimizer.step()
                self.last_loss = float(loss.detach())
        self.updates += 1
        self.rollout = []

    def state_dict(self):
        return deepcopy({"network": self.network.state_dict(), "optimizer": self.optimizer.state_dict(),
            "rng": self.rng.bit_generator.state, **{k: getattr(self, k) for k in
                ('rollout', 'updates', 'return_value', 'reward_count', 'reward_mean', 'reward_m2', 'last_loss')}})

    def load_state_dict(self, state):
        self.network.load_state_dict(state['network']); self.optimizer.load_state_dict(state['optimizer'])
        self.rng.bit_generator.state = deepcopy(state['rng'])
        for key in ('rollout', 'updates', 'return_value', 'reward_count', 'reward_mean', 'reward_m2', 'last_loss'):
            setattr(self, key, deepcopy(state[key]))
