"""N7: MEENT's hooks for old records stored without a problem and its part of the legacy runtime identity (their code is
``legacy.py``)."""
PACKAGE = __package__

CONTRIBUTION = {"legacy": {"problem": f"{PACKAGE}.legacy:problem", "runtime": f"{PACKAGE}.legacy:runtime"}}
