import type { Step } from "./types";

// Node positions on the route map. Same 14 states as machine.py, laid out like a wayfinding plan.
const NODES: Record<string, [number, number]> = {
  received: [60, 44],
  identify: [176, 44],
  load_booking: [292, 44],
  assess: [408, 44],
  entitlement: [524, 44],
  offer: [640, 44],
  read_choice: [640, 140],
  rebook: [524, 140],
  refund: [408, 140],
  voucher: [292, 140],
  handoff: [176, 140],
  compensate: [524, 236],
  notify: [292, 236],
  close: [176, 236],
  done: [60, 236],
};

// Mirrors TRANSITIONS in machine.py.
const EDGES: [string, string][] = [
  ["received", "identify"], ["identify", "load_booking"], ["identify", "handoff"],
  ["load_booking", "assess"], ["load_booking", "handoff"], ["assess", "entitlement"], ["assess", "handoff"],
  ["entitlement", "offer"], ["entitlement", "notify"], ["entitlement", "handoff"], ["offer", "read_choice"],
  ["offer", "handoff"], ["read_choice", "rebook"], ["read_choice", "refund"], ["read_choice", "voucher"],
  ["read_choice", "handoff"], ["rebook", "notify"], ["rebook", "compensate"], ["rebook", "handoff"],
  ["refund", "notify"], ["refund", "handoff"], ["voucher", "notify"], ["voucher", "handoff"],
  ["compensate", "handoff"], ["notify", "close"], ["handoff", "close"], ["close", "done"],
];

// The main route is always drawn. Escalation edges into handoff appear only when a contact takes them.
const SPINE = new Set([
  "received>identify", "identify>load_booking", "load_booking>assess", "assess>entitlement", "entitlement>offer",
  "offer>read_choice", "read_choice>rebook", "read_choice>refund", "read_choice>voucher", "rebook>notify",
  "refund>notify", "voucher>notify", "rebook>compensate", "entitlement>notify", "notify>close", "handoff>close",
  "close>done",
]);

const W = 100;
const H = 32;

// Edges that would cut through other nodes get routed around them.
function edgePath(a: string, b: string): string {
  const [x1, y1] = NODES[a];
  const [x2, y2] = NODES[b];
  if (a === "read_choice" && (b === "refund" || b === "voucher")) {
    const lift = b === "refund" ? 104 : 96;
    return `M${x1 - 20} ${y1 - H / 2} C ${x1 - 40} ${lift}, ${x2 + 40} ${lift}, ${x2 + 10} ${y2 - H / 2}`;
  }
  if (a === "read_choice" && b === "handoff") return `M${x1} ${y1 + H / 2} C ${x1} 205, ${x2} 205, ${x2} ${y2 + H / 2}`;
  if (a === "compensate" && b === "handoff") return `M${x1 - W / 2} ${y1} C 420 ${y1}, ${x2 + 20} 200, ${x2} ${y2 + H / 2}`;
  if (a === "entitlement" && b === "notify") return `M${x1} ${y1 + H / 2} C ${x1 - 40} 120, 350 190, ${x2 + 20} ${y2 - H / 2}`;
  if (y1 === y2) {
    const dir = x2 > x1 ? 1 : -1;
    return `M${x1 + (dir * W) / 2} ${y1} L ${x2 - (dir * W) / 2} ${y2}`;
  }
  if (x1 === x2) {
    const dir = y2 > y1 ? 1 : -1;
    return `M${x1} ${y1 + (dir * H) / 2} L ${x2} ${y2 - (dir * H) / 2}`;
  }
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  return `M${x1} ${y1 + (y2 > y1 ? H / 2 : -H / 2)} Q ${mx} ${my} ${x2} ${y2 + (y2 > y1 ? -H / 2 : H / 2)}`;
}

export function RouteMap({ trace, step }: { trace: Step[]; step: number }) {
  const visited = trace.slice(0, step + 1).map((s) => s.state);
  const walked = new Set<string>();
  for (let i = 1; i < visited.length; i++) walked.add(`${visited[i - 1]}>${visited[i]}`);
  const current = visited[visited.length - 1];
  const [cx, cy] = NODES[current] ?? NODES.received;
  const rejected = trace[step]?.note?.startsWith("rejected") || current === "compensate";

  return (
    <svg className="route" viewBox="0 0 760 290" role="img" aria-label={`Route through the state machine: ${visited.join(", ")}`}>
      <defs>
        <marker id="tip" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0 0L8 4L0 8z" className="tip" />
        </marker>
        <marker id="tip-on" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0 0L8 4L0 8z" className="tip-on" />
        </marker>
      </defs>
      {EDGES.map(([a, b]) => {
        const on = walked.has(`${a}>${b}`);
        if (!on && !SPINE.has(`${a}>${b}`)) return null;
        return (
          <path key={`${a}>${b}`} d={edgePath(a, b)} className={on ? "edge on" : "edge"}
            markerEnd={on ? "url(#tip-on)" : "url(#tip)"} />
        );
      })}
      {Object.entries(NODES).map(([name, [x, y]]) => {
        const cls = name === current ? "node current" : visited.includes(name) ? "node visited" : "node";
        return (
          <g key={name} className={cls}>
            <rect x={x - W / 2} y={y - H / 2} width={W} height={H} rx={6} />
            <text x={x} y={y + 4.5} textAnchor="middle">{name.replace("_", " ")}</text>
          </g>
        );
      })}
      <g className={rejected ? "marker warn" : "marker"} style={{ transform: `translate(${cx}px, ${cy - H / 2 - 9}px)` }}>
        <circle r="7" />
      </g>
    </svg>
  );
}
