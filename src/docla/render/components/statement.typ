// Statement slide: one title in a fixed frame.

#import "/lib/marks.typ": section, fit-box
#import "/lib/theme.typ": colour
#import "/lib/cite.typ": cite-keys

#let statement(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  place(top + left, dx: 40pt, dy: 120pt, fit-box("title", sec.id, 880pt, 300pt, {
    set text(size: 40pt, weight: "bold")
    sec.title
    for (i, item) in sec.items.enumerate() {
      let citations = sec.at("citations", default: ()).at(i, default: ())
      [#item.body#if citations.len() > 0 { [ #cite-keys(citations)] }]
    }
  }))
})
