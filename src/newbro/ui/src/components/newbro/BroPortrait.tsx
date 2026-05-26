import { BroAvatar, avatarTypeToCharacter } from "./BroAvatar";
import type { BroCardModel } from "./types";

export function BroPortrait({
  bro,
  active = false,
  talking,
}: {
  bro: BroCardModel;
  active?: boolean;
  talking: boolean;
}) {
  const working = active || talking || bro.status === "busy";
  const offline = bro.liveState === "offline" || bro.liveState === "unbound";
  const state = working ? "working" : offline ? "offline" : "idle";
  const tone = working ? "coral" : offline ? "soft" : "ink";

  return (
    <div className={`dt-bro-card-avatar ${working ? "dt-bro-card-avatar-info" : offline ? "dt-bro-card-avatar-warn" : ""}`}>
      <BroAvatar character={avatarTypeToCharacter(bro.avatarType)} state={state} size={40} tone={tone} />
      <span className={`dt-bro-card-pip ${working ? "dt-bro-card-pip-info" : offline ? "dt-bro-card-pip-warn" : "dt-bro-card-pip-calm"}`} />
    </div>
  );
}
