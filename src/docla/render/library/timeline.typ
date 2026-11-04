#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let timeline(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let gutter = space(1)
  let width = (content-frame.w - gutter * 5) / 6
  let date-height = content-frame.h / 5
  let item-height = content-frame.h - date-height
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    fit-box("timeline", sec.id, content-frame.w, content-frame.h, {
      grid(
        columns: (width,) * 6,
        column-gutter: gutter,
        ..items.enumerate().map(((i, item)) => {
          let citations = sec.at("citations", default: ()).at(i, default: ())
          block(width: width, height: content-frame.h, {
            fit-box("date", sec.id, width, date-height, {
              set text(..type-style("slides", "body"), fill: colour("accent"))
              el("date", sec.id, item.head, width: width)
            })
            fit-box("item", sec.id, width, item-height, {
              set text(..type-style("slides", "body"), fill: colour("ink"))
              el("item", sec.id, [#item.body #cite-keys(citations)], width: width)
            })
          })
        }),
      )
    })
    place(top + left, dy: date-height - space(1), el("rule", sec.id, line(length: content-frame.w, stroke: colour("accent"))))
  })
})
