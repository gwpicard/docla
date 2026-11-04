#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let cover(sec) = section(sec.id, {
  let paragraphs = sec.paragraphs
  let items = sec.items
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("title", sec.id, content-frame.w * 0.8, 180pt, {
      el("title", sec.id, {
        set text(..type-style("slides", "figure"), fill: colour("ink"))
        sec.title
      })
    })
  })
  if paragraphs.len() > 0 {
    place(top + left, dx: content-frame.x, dy: content-frame.y + 200pt, {
      fit-box("subtitle", sec.id, content-frame.w, 80pt, {
        el("subtitle", sec.id, {
          set text(..type-style("slides", "body"), fill: colour("ink"))
          paragraphs.first()
        })
      })
    })
  }
  place(top + left, dx: content-frame.x, dy: content-frame.y + content-frame.h - space(3), {
    el("panel", sec.id, rect(width: content-frame.w, height: space(3), fill: colour("accent"), stroke: none))
  })
  for (i, item) in items.enumerate() {
    let citations = sec.at("citations", default: ()).at(i, default: ())
    place(top + left, dx: content-frame.x, dy: content-frame.y + 290pt, {
      fit-box("item", sec.id, content-frame.w, 40pt, {
        el("item", sec.id, [#item.body #cite-keys(citations)])
      })
    })
  }
})
