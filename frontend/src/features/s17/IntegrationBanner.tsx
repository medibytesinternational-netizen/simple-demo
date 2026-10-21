import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import { bannerTone } from "./types";
import type { IntegrationStatus } from "./types";

/** One plain sentence on the hospital-system link: when it last synced and what is waiting. */
export default function IntegrationBanner() {
  const status = useQuery<IntegrationStatus>({
    queryKey: ["integration-status"],
    queryFn: () => get<IntegrationStatus>("/integrations/status"),
    refetchInterval: 30000,
  });
  if (!status.data) return null;
  return (
    <div className={`banner ${bannerTone(status.data)}`} role="status" data-testid="integration-banner">
      {status.data.banner}
      {status.data.host ? ` (${status.data.host})` : ""}
    </div>
  );
}
