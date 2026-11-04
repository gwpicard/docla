#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let image-with-text(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let image-path = sec.at("image", default: content.at("image", default: ""))
  let width = (content-frame.w - space(4)) / 2
  let title-height = 60pt
  let row-height = (content-frame.h - title-height) / 5
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("image", sec.id, width, content-frame.h, {
      el("image", sec.id, width: width, if image-path != "" {
        image(image-path, width: width, height: content-frame.h, fit: "cover")
      })
    })
  })
  place(top + left, dx: content-frame.x + width + space(4), dy: content-frame.y, {
    fit-box("body", sec.id, width, content-frame.h, {
      set block(above: 0pt, below: 0pt)
      fit-box("title", sec.id, width, title-height, {
        set text(..type-style("slides", "title"), fill: colour("ink"))
        el("title", sec.id, sec.title, width: width)
      })
      for (i, item) in items.enumerate() {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        fit-box("item", sec.id, width, row-height, {
          set text(..type-style("slides", "body"), fill: colour("ink"))
          el("item", sec.id, [#item.body #cite-keys(citations)], width: width)
        })
      }
    })
  })
})
