// d3-quadtree 3.0.1 (ISC, https://github.com/d3/d3-quadtree), src/data.js, vendored unmodified except the import paths (relative).
export default function() {
  var data = [];
  this.visit(function(node) {
    if (!node.length) do data.push(node.data); while (node = node.next)
  });
  return data;
}
