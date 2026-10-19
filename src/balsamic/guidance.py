"""Guidance with per-thread revisions.

The campaign-wide ``guidance_revision`` stays what it was: one count of the researcher's graph and page commands, which
stales every agent-prepared command. A researcher message bumps only its thread's revision, so a message in one branch
never stales the lead's work in another (docs/ui-workspace.md, M1). The lead's commands pin both from their run.
"""
from optimization_framework.campaigns.guidance import CampaignGuidance as CoreGuidance
from optimization_framework.storage.sqlite import now


class CampaignGuidance(CoreGuidance):
    def thread_revision(self, thread_id):
        try:
            return int(self.store.get(thread_id, "thread").get("guidance_revision", 0))
        except KeyError:
            return 0

    def bump_thread(self, thread_id, event="thread.guidance_changed"):
        with self.workspace.lock:
            thread = self.store.get(thread_id, "thread")
            thread["guidance_revision"] = int(thread.get("guidance_revision", 0)) + 1
            thread["updated_at"] = now()
            self.store.put("thread", thread, event)
            return thread
