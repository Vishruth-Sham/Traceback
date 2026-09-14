// Mark from "initial UI views/Modern minimal UI design/Traceback Logo (standalone).html":
// three receding square frames (brightness progression back-to-front) with a
// trace line and node on the frontmost frame. Colors per spec's light-ground variant.
export function Logo({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="40 38 158 158" className={className} aria-hidden="true">
      <path d="M80 48 L188 48 L188 132" fill="none" stroke="#92959A" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <path d="M80 48 L80 156 L134 156" fill="none" stroke="#92959A" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <path d="M65 63 L173 63 L173 147" fill="none" stroke="#5F6266" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <path d="M65 63 L65 171 L119 171" fill="none" stroke="#5F6266" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <path d="M50 78 L158 78 L158 162" fill="none" stroke="#241F1A" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <path d="M50 78 L50 186 L104 186" fill="none" stroke="#241F1A" strokeWidth={5} strokeLinejoin="round" strokeLinecap="square" />
      <line x1={104} y1={150} x2={104} y2={186} stroke="#241F1A" strokeWidth={5} strokeLinecap="round" />
      <circle cx={104} cy={150} r={7} fill="#241F1A" />
    </svg>
  );
}
