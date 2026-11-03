// Callout section: one framed block with a title and a list of items; it never breaks.

#import "/lib/marks.typ": section, el-full-width
#import "/lib/theme.typ": colour

#let callout(sec) = section(sec.id, {
  set text(size: 11pt, fill: colour("ink"))
  el-full-width("callout", sec.id, block(
    width: 100%,
    breakable: false,
    inset: 10pt,
    stroke: 1pt + colour("accent"),
    {
      text(weight: "bold", sec.title)
      for item in sec.items {
        list.item[#text(weight: "bold", item.head) #item.body]
      }
    },
  ))
})
