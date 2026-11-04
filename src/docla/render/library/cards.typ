#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let cards(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  let gap = space(3)
  let count = calc.min(calc.max(items.len(), 1), 4)
  let width = (content-frame.w - gap * (count - 1)) / count
  for (i, item) in items.enumerate() {
    let citations = sec.at("citations", default: ()).at(i, default: ())
    let height = if i >= 4 or item.body.len() > 100 { 0pt } else { content-frame.h }
    place(top + left, dx: content-frame.x + (width + gap) * calc.min(i, 3), dy: content-frame.y, {
      fit-box("item", sec.id, width, height, el("item", sec.id, {
        rect(width: width, height: content-frame.h, fill: colour("surface-alt"), stroke: none, inset: space(3), {
          fit-box("item", sec.id, width - space(3) * 2, content-frame.h - space(3) * 2, {
            set text(..type-style("slides", "body"), fill: colour("ink"))
            if item.head != none {
              strong(item.head)
              parbreak()
            }
            [#item.body #cite-keys(citations)]
          })
        })
      }))
    })
  }
})
