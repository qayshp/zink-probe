"""Read-only inspection through the portable framing layer and any byte stream."""

from ..capabilities import read_capabilities
from ..probe import negotiate, read_config, read_identity, require_select
from ..protocol import ProtocolError, validate_request
from .engine import observation
from .transport import FramedSession


class ReadOnlySession(FramedSession):
    """Enforce the existing diagnostic allowlist before a request reaches I/O.

    Capability file reads are scoped to discovered handles; no configuration
    write grants or arbitrary-command interface are exposed here.
    """

    async def exchange(self, message):
        validate_request(message, self.read_handles)
        return await super().exchange(message)


async def inspect_printer(session, expected_device_id, trace):
    """Caller owns session closure; this function never submits a print job."""
    setup = await negotiate(session, "rfcomm", trace)
    identity, errors = await read_identity(session)
    require_select(identity)
    if identity.get("device_id") != expected_device_id:
        raise ProtocolError("Wrong physical device identity")
    capabilities = await read_capabilities(session)
    if "table" not in capabilities:
        raise ProtocolError("Capabilities unavailable")
    config_before = await read_config(session)
    before = await observation(session)
    after = await observation(session)
    config_after = await read_config(session)
    return {
        "session": setup,
        "identity": identity,
        "identity_errors": errors,
        "capabilities": capabilities,
        "config_before": config_before,
        "config_after": config_after,
        "before": before,
        "after": after,
        "configuration_unchanged": config_before == config_after,
        "counters_unchanged": (before["pages"], before["calibrations"])
        == (after["pages"], after["calibrations"]),
        "target_events": [data.hex() for data in session.events],
    }
