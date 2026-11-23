import { useSearchParams } from "react-router-dom";
import { ClaimReview } from "../features/f12/ClaimReview";
import { LeakageView } from "../features/f13/LeakageView";
import { Tabs } from "../components/ui";

/**
 * /revenue: Claim review (?tab=claim, the default) and Revenue leakage (?tab=leakage). Each tab is
 * its own view (features/f12/ClaimReview.tsx, features/f13/LeakageView.tsx); this page only keeps
 * the shared tab strip and the existing ?tab= routing.
 */
export function RevenuePage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "claim";
  const tabItems = [
    { key: "claim", label: "Claim review" },
    { key: "leakage", label: "Revenue leakage" },
  ];
  const tabStrip = <Tabs label="Revenue" items={tabItems} value={(tab === "leakage" ? "leakage" : "claim") as string} onSelect={(key) => setParams({ tab: key })} />;

  return tab === "leakage" ? <LeakageView tabs={tabStrip} /> : <ClaimReview tabs={tabStrip} />;
}
