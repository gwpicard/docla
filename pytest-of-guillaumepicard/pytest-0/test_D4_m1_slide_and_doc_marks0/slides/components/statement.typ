// Statement slide: one title in a fixed frame.

#import "/lib/marks.typ": section, fit-box
#import "/lib/theme.typ": colour

#let statement(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  place(top + left, dx: 40pt, dy: 120pt, fit-box("title", sec.id, 880pt, 300pt, {
    set text(size: 40pt, weight: "bold")
    sec.title
  }))
})
