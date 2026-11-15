// d3-quadtree 3.0.1 (ISC, https://github.com/d3/d3-quadtree), src/size.js, vendored unmodified except the import paths (relative).
export default function() {
  var size = 0;
  this.visit(function(node) {
    if (!node.length) do ++size; while (node = node.next)
  });
  return size;
}
