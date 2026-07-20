export type CabinDestination = "bridge" | "navigator" | "oracle" | "council" | "sentry" | "admiral" | "logbook" | "config";

const DESTINATIONS: readonly { id: CabinDestination; title: string; subtitle: string }[] = [
  { id: "bridge", title: "Bridge", subtitle: "Full cabin" },
  { id: "navigator", title: "Navigator", subtitle: "Shadow plan" },
  { id: "oracle", title: "Oracle", subtitle: "Intelligence" },
  { id: "council", title: "Council", subtitle: "Synthesis" },
  { id: "sentry", title: "Sentry", subtitle: "Warnings" },
  { id: "admiral", title: "Admiral", subtitle: "Not included" },
  { id: "logbook", title: "Logbook", subtitle: "Mission record" },
  { id: "config", title: "Config", subtitle: "Not included" },
];

export function BottomNavigation({ active, onNavigate }: { active: CabinDestination; onNavigate: (id: CabinDestination) => void }) {
  return (
    <nav className="bottom-navigation" aria-label="Captain's Cabin presentation navigation">
      {DESTINATIONS.map((destination) => (
        <button
          key={destination.id}
          type="button"
          className={active === destination.id ? "is-active" : ""}
          aria-current={active === destination.id ? "page" : undefined}
          onClick={() => onNavigate(destination.id)}
        >
          <strong>{destination.title}</strong>
          <span>{destination.subtitle}</span>
        </button>
      ))}
    </nav>
  );
}
