// When the transcript viewer scrolls its list to the end. Pure: no Herdr imports, so the tests run it
// under node.
//
// The transcript is a virtual list (the only kind with scroll_to_bottom to jump to the end), and it places
// rows by heights the viewer states. Those heights are measured after the rows are laid out, so a jump
// to the end made before every height is known lands short. A jump that was asked for (opening, new
// entries while following, the Follow button, a resize while following) is therefore repeated on each
// frame until no row is waiting to be measured, then dropped.
//
//   follow      the viewer is following the end (scrolling up turns it off)
//   want        a jump to the end was asked for and has not landed yet
//   unmeasured  rows whose height is not known yet
// Returns { scroll: jump on this frame, want: the new value of `want` }.
export function endStep({ follow, want, unmeasured }) {
  if (!follow || !want) return { scroll: false, want: false };
  return { scroll: true, want: unmeasured > 0 };
}

// Rows' heights for the virtual list: measured where known, a guess where not (they are measured on the
// next frame), and the trailing spacer.
export const GUESS_H = 32;
export const END_H = 14;
export function rowHeights(count, heightOf) {
  const out = new Array(count + 1);
  for (let i = 0; i < count; i++) out[i] = heightOf(i) ?? GUESS_H;
  out[count] = END_H;
  return out;
}
