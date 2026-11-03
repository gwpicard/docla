#set page(paper: "a4", margin: 54pt, columns: 2)
#set columns(gutter: 18pt)
#import "lib/marks.typ": *
#set text(size: 10pt, costs: (widow: 0%, orphan: 0%))
#context [#metadata((kind: "calib", one: measure(block(width: 234pt, [x])).height / 1pt, two: measure(block(width: 234pt, [x \ x])).height / 1pt, head: measure(block(width: 234pt, text(size: 13pt, weight: "bold")[H])).height / 1pt)) <docla-mark>]
#v(100pt)
#el("para", "p00", [a0 a1 \ b0 b1 \ c0 c1], width: 234pt)
#el("para", "p01", [d0 d1 \ e0 e1], width: 234pt)
