// Callout section: one framed block with a title and a list of items; it never breaks.

#import "/lib/marks.typ": section, el-full-width
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let callout(sec) = section(sec.id, {
  set text(..type-style("doc", "body"), fill: colour("ink"))
  el-full-width("callout", sec.id, block(
    width: 100%,
    breakable: false,
    inset: space(5),
    stroke: 1pt + colour("accent"),
    {
      text(weight: "bold", sec.title)
      for (i, item) in sec.items.enumerate() {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        list.item[#text(weight: "bold", item.head) #item.body#if citations.len() > 0 { [ #cite-keys(citations)] }]
      }
    },
  ))
})
