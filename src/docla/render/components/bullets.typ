// Bullets slide: a title and a list of items, each in a fixed frame.

#import "/lib/marks.typ": section, el, el-full-width, fit-box
#import "/lib/theme.typ": colour, type-style
#import "/lib/frames.typ": title-frame, content-frame
#import "/lib/cite.typ": cite-keys

#let bullets(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  place(top + left, dx: title-frame.x, dy: title-frame.y + type-style("slides", "title").size / 20, fit-box("title", sec.id, title-frame.w, title-frame.h, {
    set text(..type-style("slides", "title"))
    el("title", sec.id, sec.title)
  }))
  place(top + left, dx: content-frame.x, dy: content-frame.y, fit-box("body", sec.id, content-frame.w, content-frame.h, {
    set text(..type-style("slides", "body"))
    for (i, item) in sec.items.enumerate() {
      let citations = sec.at("citations", default: ()).at(i, default: ())
      el-full-width("item", sec.id, [#text(weight: "bold", item.head) #item.body#if citations.len() > 0 { [ #cite-keys(citations)] }])
    }
  }))
})
