#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let matrix(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let data = if sec.data == none { (:) } else { sec.data }
  let label-height = space(4)
  let gutter = space(2)
  let width = (content-frame.w - gutter) / 2
  let height = (content-frame.h - label-height - gutter) / 2
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    set text(..type-style("slides", "body"), fill: colour("ink"))
    grid(
      columns: (width, width),
      column-gutter: gutter,
      row-gutter: gutter,
      ..items.enumerate().map(((i, item)) => {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        fit-box("item", sec.id, width, if item.head.len() + item.body.len() > 70 { 0pt } else { height },
          el("quadrant", sec.id, {
            if item.head != "" { strong(item.head); linebreak() }
            [#item.body #cite-keys(citations)]
          }, width: width))
      }),
    )
    grid(
      columns: (width, width),
      column-gutter: gutter,
      ..("x", "y").map(key => {
        if data.at(key, default: "") != "" {
          fit-box("axis-label", sec.id, width, label-height,
            el("axis-label", sec.id, str(data.at(key)), width: width))
        } else { [] }
      }),
    )
  })
})
