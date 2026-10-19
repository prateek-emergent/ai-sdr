"""One-time LiveKit telephony setup: outbound trunk (to Twilio Elastic SIP), inbound trunk + dispatch rule.

Twilio side (do first, in the Twilio console):
  1. Buy the US number (office area code).
  2. Elastic SIP Trunking -> create trunk.
     Termination: set a termination URI (e.g. emergent-sdr.pstn.twilio.com) + a credential list
                  (username/password used below).
     Origination: add your LiveKit SIP URI (Project settings -> SIP URI) as origination URI.
  3. Attach the number to the trunk.
"""
from __future__ import annotations

import json

from livekit import api

from .config import settings


async def setup(termination_uri: str, username: str, password: str) -> dict:
    s = settings()
    if not s.caller_number:
        raise SystemExit("Set CALLER_NUMBER (the +1 number) first")
    lk = api.LiveKitAPI(url=s.livekit_url, api_key=s.livekit_api_key, api_secret=s.livekit_api_secret)
    try:
        out = await lk.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(
            trunk=api.SIPOutboundTrunkInfo(name="ai-sdr-twilio-out", address=termination_uri,
                                           numbers=[s.caller_number], auth_username=username,
                                           auth_password=password)))
        inbound = await lk.sip.create_sip_inbound_trunk(api.CreateSIPInboundTrunkRequest(
            trunk=api.SIPInboundTrunkInfo(name="ai-sdr-twilio-in", numbers=[s.caller_number])))
        rule = await lk.sip.create_sip_dispatch_rule(api.CreateSIPDispatchRuleRequest(
            name="ai-sdr-inbound",
            trunk_ids=[inbound.sip_trunk_id],
            rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="sdr-in-")),
            room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(
                agent_name=s.agent_name, metadata=json.dumps({"direction": "inbound"}))])))
    finally:
        await lk.aclose()
    return {"SIP_OUTBOUND_TRUNK_ID": out.sip_trunk_id, "inbound_trunk_id": inbound.sip_trunk_id,
            "dispatch_rule_id": rule.sip_dispatch_rule_id}
