// d3-quadtree 3.0.1 (ISC, https://github.com/d3/d3-quadtree), src/extent.js, vendored unmodified except the import paths (relative).
export default function(_) {
  return arguments.length
      ? this.cover(+_[0][0], +_[0][1]).cover(+_[1][0], +_[1][1])
      : isNaN(this._x0) ? undefined : [[this._x0, this._y0], [this._x1, this._y1]];
}
