// Bullets slide: a title and a list of items, each in a fixed frame.

#import "/lib/marks.typ": section, el, fit-box
#import "/lib/theme.typ": colour

#let bullets(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  place(top + left, dx: 40pt, dy: 40pt, fit-box("title", sec.id, 880pt, 60pt, {
    set text(size: 32pt, weight: "bold")
    sec.title
  }))
  place(top + left, dx: 40pt, dy: 120pt, fit-box("body", sec.id, 880pt, 380pt, {
    set text(size: 20pt)
    for item in sec.items {
      el("item", sec.id, width: 100%, [#text(weight: "bold", item.head) #item.body])
    }
  }))
})
