from collections import defaultdict
from dataclasses import dataclass, field

from boneio.relay.basic import BasicRelay


@dataclass
class SoftwareInterlockManager:
    groups: defaultdict[str, set[BasicRelay]] = field(
        default_factory=lambda: defaultdict(set)
    )

    def register(self, relay: BasicRelay, group_names: list[str]) -> None:
        for group in group_names:
            self.groups[group].add(relay)

    def can_turn_on(self, relay: BasicRelay, group_names: list[str]) -> bool:
        for group in group_names:
            for other_relay in self.groups.get(group, []):
                if (
                    other_relay is not relay
                    and getattr(other_relay, "state", None) == "ON"
                ):
                    return False
        return True
