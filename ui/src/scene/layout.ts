import type { CSSProperties } from "react";

/**
 * All scene coordinates are percentages of the 1448 x 1086 reference canvas.
 * Keeping the geometry here makes the cabin responsive without coupling it to
 * mission data or scattering calibration values through components.
 */
export type SceneRegion = {
  id: string;
  left: number;
  top: number;
  width: number;
  height: number;
  rotate?: number;
  zIndex?: number;
};

export type StageBookId =
  | "harbormaster"
  | "oracle"
  | "council"
  | "governor"
  | "navigator";

export type SceneRegionId =
  | "top-status"
  | "harbormaster-book"
  | "oracle-book"
  | "council-book"
  | "governor-book"
  | "navigator-book"
  | "sentry-alerts"
  | "market-conditions"
  | "captains-log"
  | "mission-chart"
  | "paper-order"
  | "systems-panel"
  | "bottom-navigation";

export const STAGE_BOOK_IDS = [
  "harbormaster",
  "oracle",
  "council",
  "governor",
  "navigator",
] as const satisfies readonly StageBookId[];

export const SCENE_REGIONS = {
  "top-status": {
    id: "top-status",
    left: 29.56,
    top: 5.34,
    width: 40.33,
    height: 14.55,
    rotate: -0.1,
    zIndex: 10,
  },
  "harbormaster-book": {
    id: "harbormaster-book",
    left: 6.77,
    top: 23.94,
    width: 17.2,
    height: 28.73,
    rotate: -1.8,
    zIndex: 12,
  },
  "oracle-book": {
    id: "oracle-book",
    left: 24.17,
    top: 23.2,
    width: 16.02,
    height: 29.01,
    rotate: -2.7,
    zIndex: 13,
  },
  "council-book": {
    id: "council-book",
    left: 41.23,
    top: 23.3,
    width: 14.3,
    height: 28.45,
    rotate: 0.5,
    zIndex: 14,
  },
  "governor-book": {
    id: "governor-book",
    left: 55.73,
    top: 23.3,
    width: 14.57,
    height: 28.27,
    rotate: 0.8,
    zIndex: 15,
  },
  "navigator-book": {
    id: "navigator-book",
    left: 70.79,
    top: 23.94,
    width: 10.36,
    height: 27.35,
    rotate: 1.1,
    zIndex: 16,
  },
  "sentry-alerts": {
    id: "sentry-alerts",
    left: 2.76,
    top: 55.34,
    width: 18.65,
    height: 18.6,
    rotate: -3.6,
    zIndex: 11,
  },
  "market-conditions": {
    id: "market-conditions",
    left: 3.25,
    top: 74.77,
    width: 18.09,
    height: 13.44,
    rotate: -0.7,
    zIndex: 11,
  },
  "captains-log": {
    id: "captains-log",
    left: 24.79,
    top: 53.59,
    width: 22.17,
    height: 33.24,
    rotate: -0.3,
    zIndex: 12,
  },
  "mission-chart": {
    id: "mission-chart",
    left: 48.14,
    top: 53.59,
    width: 19.34,
    height: 32.6,
    rotate: 0.2,
    zIndex: 11,
  },
  "paper-order": {
    id: "paper-order",
    left: 66.92,
    top: 55.52,
    width: 13.95,
    height: 30.11,
    rotate: 1,
    zIndex: 12,
  },
  "systems-panel": {
    id: "systems-panel",
    left: 81.98,
    top: 20.07,
    width: 16.78,
    height: 68.6,
    zIndex: 12,
  },
  "bottom-navigation": {
    id: "bottom-navigation",
    left: 1.73,
    top: 91.25,
    width: 96.96,
    height: 6.63,
    zIndex: 30,
  },
} as const satisfies Record<SceneRegionId, SceneRegion>;

/** Usable ink areas, inset from the illustrated book headings and bindings. */
export const STAGE_CONTENT_REGIONS = {
  harbormaster: {
    id: "harbormaster-content",
    left: 8.7,
    top: 32.14,
    width: 13.74,
    height: 17.13,
    rotate: -1.8,
    zIndex: 14,
  },
  oracle: {
    id: "oracle-content",
    left: 25.69,
    top: 30.66,
    width: 13.33,
    height: 18.14,
    rotate: -2.7,
    zIndex: 15,
  },
  council: {
    id: "council-content",
    left: 42.68,
    top: 31.03,
    width: 11.46,
    height: 17.86,
    rotate: 0.5,
    zIndex: 16,
  },
  governor: {
    id: "governor-content",
    left: 57.39,
    top: 31.03,
    width: 11.46,
    height: 17.5,
    rotate: 0.8,
    zIndex: 17,
  },
  navigator: {
    id: "navigator-content",
    left: 71.89,
    top: 30.66,
    width: 7.87,
    height: 17.4,
    rotate: 1.1,
    zIndex: 18,
  },
} as const satisfies Record<StageBookId, SceneRegion>;

export const LOWER_CONTENT_REGIONS = {
  "sentry-alerts": {
    id: "sentry-alerts-content",
    left: 4.01,
    top: 57.55,
    width: 16.3,
    height: 14.46,
    rotate: -3.6,
    zIndex: 13,
  },
  "market-conditions": {
    id: "market-conditions-content",
    left: 5.11,
    top: 76.8,
    width: 14.71,
    height: 10.13,
    rotate: -0.7,
    zIndex: 13,
  },
  "captains-log": {
    id: "captains-log-content",
    left: 26.31,
    top: 55.8,
    width: 19.2,
    height: 29.1,
    rotate: -0.3,
    zIndex: 14,
  },
  "mission-chart": {
    id: "mission-chart-content",
    left: 49.24,
    top: 55.8,
    width: 16.37,
    height: 26.34,
    rotate: 0.2,
    zIndex: 13,
  },
  "paper-order": {
    id: "paper-order-content",
    left: 68.02,
    top: 58.75,
    width: 11.53,
    height: 23.57,
    rotate: 1,
    zIndex: 14,
  },
} as const satisfies Record<
  "sentry-alerts" | "market-conditions" | "captains-log" | "mission-chart" | "paper-order",
  SceneRegion
>;

export const STATUS_SLOTS = {
  marketRegime: { id: "market-regime", left: 31.08, top: 9.3, width: 7.6, height: 4.97 },
  fleetStatus: { id: "fleet-status", left: 40.54, top: 9.3, width: 8.7, height: 4.05 },
  modeldock: { id: "modeldock-status", left: 50.62, top: 9.3, width: 8.63, height: 4.05 },
  snapshotCount: { id: "snapshot-count", left: 62.64, top: 9.3, width: 4.28, height: 3.8 },
  currentMission: { id: "current-mission", left: 40.4, top: 15.75, width: 12.4, height: 2.76 },
  shadowMode: { id: "shadow-mode", left: 54.97, top: 15.75, width: 4.21, height: 2.76 },
  timestamp: { id: "mission-timestamp", left: 62.3, top: 15.2, width: 4.8, height: 3.3 },
} as const satisfies Record<string, SceneRegion>;

export const NAVIGATION_REGIONS = {
  bridge: { id: "nav-bridge", left: 1.8, top: 91.25, width: 12.7, height: 6.63, zIndex: 31 },
  navigator: { id: "nav-navigator", left: 14.78, top: 91.25, width: 12.09, height: 6.63, zIndex: 31 },
  oracle: { id: "nav-oracle", left: 27.21, top: 91.25, width: 11.39, height: 6.63, zIndex: 31 },
  council: { id: "nav-council", left: 38.74, top: 91.25, width: 11.6, height: 6.63, zIndex: 31 },
  sentry: { id: "nav-sentry", left: 50.41, top: 91.25, width: 11.33, height: 6.63, zIndex: 31 },
  admiral: { id: "nav-admiral", left: 61.95, top: 91.25, width: 11.6, height: 6.63, zIndex: 31 },
  logbook: { id: "nav-logbook", left: 73.69, top: 91.25, width: 12.22, height: 6.63, zIndex: 31 },
  config: { id: "nav-config", left: 86.05, top: 91.25, width: 12.43, height: 6.63, zIndex: 31 },
} as const satisfies Record<string, SceneRegion>;

export type SceneRegionStyle = CSSProperties & {
  "--scene-rotation": string;
};

export function regionStyle(region: SceneRegion): SceneRegionStyle {
  return {
    left: `${region.left}%`,
    top: `${region.top}%`,
    width: `${region.width}%`,
    height: `${region.height}%`,
    zIndex: region.zIndex,
    "--scene-rotation": `${region.rotate ?? 0}deg`,
  };
}
