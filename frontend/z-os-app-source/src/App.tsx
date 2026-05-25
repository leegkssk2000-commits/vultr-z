import { useZosLiveContract, LiveApiLockCard } from './app/live/zLiveContract';
import './app/live/zLiveContract.css';
import { useEffect, useMemo, useState, type ReactNode } from "react";
import "./App.css";
import { ZopsSafeBoundary, ZopsSafeBlock } from "./app/components/safety/ZopsSafeBoundary";
import { ZuiSafeBoundary, ZuiSafeBlock } from "./app/components/safety/ZuiSafeBoundary";
import "./app/components/safety/ZuiSafeBoundary.css";
import { ActionGuardPanel } from "./app/components/rebase/ActionGuardPanel";
import { AppFrame, type AppTabId } from "./app/components/rebase/AppFrame";
import { BotFamilyHub } from "./app/components/rebase/BotFamilyHub";
import { CandidateFlowPanel } from "./app/components/rebase/CandidateFlowPanel";
import { CandidateLaneFlow } from "./app/components/rebase/CandidateLaneFlow";
import { Chip, Kicker, Panel } from "./app/components/rebase/UiPrimitives";
import { ClickableEvidenceReplay } from "./app/components/rebase/ClickableEvidenceReplay";
import { CurrentTradingTeamCard } from "./app/components/rebase/CurrentTradingTeamCard";
import { LicoGuard, LicoStatusMini, LicoStrip, LicoTrace } from "./app/components/lico/Lico2BIntegrated";
import { DecisionWorkbenchSummary } from "./app/components/rebase/DecisionWorkbenchSummary";
import { EvidenceChainPanel } from "./app/components/rebase/EvidenceChainPanel";
import { FinalDashboardHero } from "./app/components/rebase/FinalDashboardHero";
import { FinalOperatingSnapshot } from "./app/components/rebase/FinalOperatingSnapshot";
import { FinalRuntimeLocks } from "./app/components/rebase/FinalRuntimeLocks";
import { FinalRuntimeToggles } from "./app/components/rebase/FinalRuntimeToggles";
import { GlobalProvenanceFooter } from "./app/components/rebase/GlobalProvenanceFooter";
import { MarketProjectionGrid } from "./app/components/rebase/MarketProjectionGrid";
import { OrderbookPanel } from "./app/components/rebase/OrderbookPanel";
import { NativeAdvancedChart } from "./app/components/rebase/NativeAdvancedChart";
import { OperatingConstitutionPanel } from "./app/components/rebase/OperatingConstitutionPanel";
import { ProjectionCalloutCard } from "./app/components/rebase/ProjectionCalloutCard";
import { ProjectionEnvelopeCard } from "./app/components/rebase/ProjectionEnvelopeCard";
import { RuntimePolicyStateBoard } from "./app/components/rebase/RuntimePolicyStateBoard";
import { SurfaceCapabilityMatrix } from "./app/components/rebase/SurfaceCapabilityMatrix";
import { TeamEntryConditionPanel } from "./app/components/rebase/TeamEntryConditionPanel";
import { TeamIntelligenceSection } from "./app/components/rebase/TeamIntelligenceSection";
import { ZbotSpinePanel } from "./app/components/rebase/ZbotSpinePanel";
import { ZliceProofCapsule } from "./app/components/rebase/ZliceProofCapsule";
import { zliceEvidenceDrawer } from "./app/data/operatingConstitution";
import { provenanceFooter } from "./app/data/projectionEvidence";
import "./app/patches/zuiLayoutRecovery.css";
import "./app/patches/zuiMatrixLicoWidthPolish.css";
import "./app/patches/zuiRuntimeLockRowRestore.css";
import AlimiBridge from "./app/components/alimi/AlimiBridge";
import AlimiMessageDeck from "./app/components/alimi/AlimiMessageDeck";
import AlimiCornerRail from "./app/components/alimi/AlimiCornerRail";
import AlimiDomainGate from "./app/components/alimi/AlimiDomainGate";
import { isAlimiDomainHost } from "./app/domain/alimiDomain";
import "./app/patches/zuiTeamOverlayModalV4.css";
import "./app/patches/zuiTeamOverlayModalV4";
import AlimiNotificationSurface from "./app/components/alimi/AlimiNotificationSurface";
import "./app/components/alimi/AlimiOnlySurface.css";
import QiReadinessStrip from "./app/components/qi/QiReadinessStrip";
import LicoMarketSafetyStrip from "./app/components/lico/LicoMarketSafetyStrip";
// ZUI_DISABLED_TEAM_OVERLAY_V4 import "./app/patches/zuiTeamOverlayClickLockRepair";
// ZUI_DISABLED_TEAM_OVERLAY_V4 import "./app/patches/zuiTeamOverlayRuntimeForcefix";
// ZUI_DISABLED_TEAM_OVERLAY_V4 import "./app/patches/zuiTeamOverlayFinalV3.css";
// ZUI_DISABLED_TEAM_OVERLAY_V4 import "./app/patches/zuiTeamOverlayFinalV3.ts";

// ZUI_SETTINGS_SAFE_FIX_V1
// ZOPS_SETTINGS_STABILITY_HARNESS_V1
type ViewConfig = {
  tab: AppTabId;
  children: ReactNode;
};

const tabs: AppTabId[] = ["dashboard", "trade", "log", "settings", "bots"];

function readTabFromHash(): AppTabId {
  if (typeof window === "undefined") return "dashboard";
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const tab = params.get("tab") as AppTabId | null;
  if (tab && tabs.includes(tab)) return tab;
  return isAlimiDomainHost() ? "settings" : "dashboard";
}

function toneForTimelineState(state: string): "ok" | "watch" | "proof" {
  if (state === "verified") return "proof";
  if (state === "watch") return "watch";
  return "ok";
}

function ProvenanceChainViewer() {
  return (
    <Panel className="zr-log-restore-panel">
      <Kicker>full provenance chain viewer</Kicker>
      <div className="zr-title">{provenanceFooter.provenanceChainId}</div>
      <div className="zr-sub">{provenanceFooter.lineage}</div>
      <div className="zr-chip-row zr-log-chip-row">
        <Chip>{provenanceFooter.decisionId}</Chip>
        <Chip tone="proof">{provenanceFooter.zbotSignature}</Chip>
      </div>
    </Panel>
  );
}

function ReceiptArchivePreview() {
  return (
    <Panel className="zr-log-restore-panel">
      <Kicker>receipt archive preview</Kicker>
      <div className="zr-policy-grid zr-log-archive-grid">
        {zliceEvidenceDrawer.receiptArchive.map((item) => (
          <div className="zr-policy-row" key={item.label}>
            <div className="zr-title">{item.label}</div>
            <div className="zr-sub">{item.value}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ReplayTimelinePreview() {
  return (
    <Panel className="zr-log-restore-panel zr-log-timeline-panel">
      <Kicker>replay timeline</Kicker>
      <div className="zr-timeline">
        {zliceEvidenceDrawer.replayTimeline.map((item) => (
          <div className="zr-timeline-item" key={`${item.time}-${item.event}`}>
            <div className="zr-sub">{item.time}</div>
            <div>
              <div className="zr-title">{item.event}</div>
              <Chip tone={toneForTimelineState(item.state)}>{item.state}</Chip>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function DashboardView() {
  return (
    <div className="zr-stack" aria-label="Dashboard operational view">
      <FinalDashboardHero />
      <QiReadinessStrip />
      <LicoMarketSafetyStrip />
      <FinalOperatingSnapshot />
      <ProjectionEnvelopeCard />
      <ProjectionCalloutCard />
      <LicoStrip surface="dashboard" />
      <ZliceProofCapsule compact />
      <MarketProjectionGrid />
      <OrderbookPanel />
      <CurrentTradingTeamCard />
      <CandidateLaneFlow />
      <ZuiSafeBlock name="GlobalProvenanceFooter"><GlobalProvenanceFooter /></ZuiSafeBlock>
    </div>
  );
}

function TradeView() {
  return (
    <div className="zr-stack" aria-label="Trade projection view">
      <ProjectionCalloutCard />
      <NativeAdvancedChart />
      <DecisionWorkbenchSummary />
      <ActionGuardPanel />
      <LicoGuard />
      <ZuiSafeBlock name="GlobalProvenanceFooter"><GlobalProvenanceFooter /></ZuiSafeBlock>
    </div>
  );
}

function LogView() {
  return (
    <div className="zr-stack" aria-label="Evidence replay log view">
      <ClickableEvidenceReplay />
      <EvidenceChainPanel />
      <LicoTrace />
      <ProvenanceChainViewer />
      <ReceiptArchivePreview />
      <ReplayTimelinePreview />
      <ZuiSafeBlock name="GlobalProvenanceFooter"><GlobalProvenanceFooter /></ZuiSafeBlock>
    </div>
  );
}

function SettingsView() {
  const isAlimiDomain = isAlimiDomainHost();
  return (
    <div className="zr-stack" aria-label="Governance settings view">
      {isAlimiDomain ? (
        <ZopsSafeBlock name="settings:AlimiDomainGate"><AlimiDomainGate /></ZopsSafeBlock>
      ) : null}
      <ZopsSafeBlock name="settings:FinalRuntimeLocks"><FinalRuntimeLocks /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:FinalRuntimeToggles"><FinalRuntimeToggles /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:LicoStatusMini"><LicoStatusMini /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:RuntimePolicyStateBoard"><RuntimePolicyStateBoard /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:SurfaceCapabilityMatrix"><SurfaceCapabilityMatrix /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:OperatingConstitutionPanel"><OperatingConstitutionPanel /></ZopsSafeBlock>
      <ZopsSafeBlock name="settings:GlobalProvenanceFooter"><GlobalProvenanceFooter /></ZopsSafeBlock>
    </div>
  );
}

function BotsView() {
  return (
    <div className="zr-stack" aria-label="Bots and team routing view">
      <ZbotSpinePanel />
      <BotFamilyHub />
      <TeamEntryConditionPanel />
      <CandidateFlowPanel />
      <TeamIntelligenceSection />
      <ZuiSafeBlock name="GlobalProvenanceFooter"><GlobalProvenanceFooter /></ZuiSafeBlock>
    </div>
  );
}

function AlimiOnlyView() {
  return (
    <main className="alimi-only-shell" data-zops-alimi-only="v2">
      <div className="alimi-only-frame">
        <div className="alimi-only-topline">
          <div>
            <b>ALIMI ONLY SURFACE</b>
            <span>external notify · violation-only · bundle/suppress · TradingView replay context</span>
          </div>
          <span className="alimi-only-lock">isolated</span>
        </div>
        <ZopsSafeBlock name="alimi-only:DomainGate"><AlimiDomainGate /></ZopsSafeBlock>
        <ZopsSafeBlock name="alimi-only:NotificationReplay"><AlimiNotificationSurface /></ZopsSafeBlock>
      </div>
    </main>
  );
}

function ZopsOperationalApp() {
  const alimiOnlySurface = isAlimiDomainHost();
  useEffect(() => {
    document.body.dataset.zopsSurface = alimiOnlySurface ? "alimi-only" : "app";
    return () => { delete document.body.dataset.zopsSurface; };
  }, [alimiOnlySurface]);
  const zLive = useZosLiveContract();
  const [activeTab, setActiveTab] = useState<AppTabId>(() => readTabFromHash());

  useEffect(() => {
    const onHashChange = () => setActiveTab(readTabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const view = useMemo<ViewConfig>(() => {
    switch (activeTab) {
      case "trade":
        return { tab: "trade", children: <TradeView /> };
      case "log":
        return { tab: "log", children: <LogView /> };
      case "settings":
        return { tab: "settings", children: <SettingsView /> };
      case "bots":
        return { tab: "bots", children: <BotsView /> };
      case "dashboard":
      default:
        return { tab: "dashboard", children: <DashboardView /> };
    }
  }, [activeTab]);

  if (alimiOnlySurface) return <AlimiOnlyView />;



  return <AppFrame activeTab={view.tab}><ZopsSafeBoundary name={`tab:${view.tab}`} resetKey={view.tab}>{view.children}</ZopsSafeBoundary></AppFrame>;
}

// ZOPS_ALIMI_SOURCE_ROUTE_BEGIN
function isZopsAlimiOnlySurface(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname.toLowerCase();
  const metaSurface = document.querySelector<HTMLMetaElement>('meta[name="zops-surface-id"]')?.content?.toLowerCase();
  const bodySurface = document.body?.dataset?.zopsSurface?.toLowerCase();
  return metaSurface === "alimi" || bodySurface === "alimi" || host === "alimi.z-os.vip" || host.startsWith("alimi.");
}

function ZopsAlimiOnlySurface() {
  return (
    <ZopsSafeBoundary name="surface:alimi-only">
      <AlimiCornerRail />
      <main className="zr-alimi-only-route" data-zops-surface="alimi" data-zops-owner="alimi">
        <AlimiBridge />
        <AlimiMessageDeck />
      </main>
    </ZopsSafeBoundary>
  );
}

export default function App() {
  if (isZopsAlimiOnlySurface()) return <ZopsAlimiOnlySurface />;
  return <ZopsOperationalApp />;
}
// ZOPS_ALIMI_SOURCE_ROUTE_END

