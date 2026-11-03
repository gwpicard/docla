// Callout section: one framed block with a title and a list of items; it never breaks.

#import "/lib/marks.typ": section, el
#import "/lib/theme.typ": colour

#let callout(sec) = section(sec.id, {
  set text(size: 11pt, fill: colour("ink"))
  // `el` measures outside any container, where 100% resolves to 0, so pass the text width.
  layout(size => el("callout", sec.id, width: size.width, block(
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
  )))
})
