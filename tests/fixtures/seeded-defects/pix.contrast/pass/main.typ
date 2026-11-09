#import "/lib/marks.typ": section, el
#set page(width: 960pt, height: 540pt, margin: 0pt, fill: white)
#section("s1")[
  #place(top + left, dx: 40pt, dy: 40pt, rect(width: 880pt, height: 460pt, fill: rgb("#1A1A1A"), stroke: none))
  #place(top + left, dx: 80pt, dy: 80pt, el("body", "s1", text(font: "Inter", size: 24pt, fill: rgb("#FFFFFF"))[Contrast sample]))
]
