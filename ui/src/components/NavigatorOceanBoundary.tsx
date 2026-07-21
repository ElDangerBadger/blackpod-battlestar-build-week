import {
  Component,
  Suspense,
  lazy,
  useMemo,
  useState,
  type ComponentType,
  type ErrorInfo,
  type ReactNode,
} from "react";

import { NavigatorShipView } from "./NavigatorShipView";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";

type OceanModule = { default: ComponentType<NavigatorOceanViewProps> };
type OceanLoader = () => Promise<OceanModule>;

export type NavigatorOceanBoundaryProps = NavigatorOceanViewProps & Readonly<{
  capabilityProbe?: () => boolean;
  loadView?: OceanLoader;
}>;

const defaultLoader: OceanLoader = () => import("./navigator-ocean/NavigatorOceanView");

export function supportsWebGL(): boolean {
  if (typeof document === "undefined") return false;
  if (typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("jsdom")) return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

class OceanErrorBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // The user-facing fallback is intentionally sanitized; no mission data changes.
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function OceanFallback({ props, reason }: { props: NavigatorOceanViewProps; reason: string }) {
  const latest = props.data.points.at(-1) ?? null;
  return (
    <section className="navigator-ocean-fallback" aria-label="Navigator canonical chart fallback">
      <p role="status"><strong>3D ocean unavailable; canonical chart shown.</strong> {reason}</p>
      <p>
        Latest captured bar: {latest ? new Date(latest.t * 1000).toISOString() : "Not present in mission artifact"} · {props.presentationMode} · {props.runMode}
      </p>
      {props.data.summary.last_ma === null ? (
        <p>Final supplied MA{props.data.ma_period}: unavailable. No value was inferred or substituted.</p>
      ) : null}
      <NavigatorShipView data={props.data} variant="interactive" />
    </section>
  );
}

/** Eager, lightweight gate. The Three.js module is requested only after expansion and capability checks. */
export function NavigatorOceanBoundary({
  capabilityProbe = supportsWebGL,
  loadView = defaultLoader,
  ...props
}: NavigatorOceanBoundaryProps) {
  const [runtimeUnavailable, setRuntimeUnavailable] = useState(false);
  const capability = useMemo(() => capabilityProbe(), [capabilityProbe]);
  const LazyOcean = useMemo(() => lazy(loadView), [loadView]);
  const fallback = <OceanFallback props={props} reason="The read-only SVG view preserves the same supplied observations." />;

  if (!capability || runtimeUnavailable) return fallback;

  return (
    <OceanErrorBoundary fallback={fallback}>
      <Suspense fallback={<p className="navigator-ocean-loading" role="status">Loading cinematic Navigator ocean…</p>}>
        <LazyOcean {...props} onRuntimeUnavailable={() => setRuntimeUnavailable(true)} />
      </Suspense>
    </OceanErrorBoundary>
  );
}
