// Body section: a title and paragraphs that flow across pages.

#import "/lib/marks.typ": section, el
#import "/lib/theme.typ": colour

// `el` measures outside any container, where 100% resolves to 0, so pass the text width.
#let _full(role, id, content) = layout(size => el(role, id, width: size.width, content))

#let body(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  _full("heading", sec.id, {
    set text(size: 16pt, weight: "bold")
    sec.title
  })
  set text(size: 11pt)
  for p in sec.paragraphs {
    par(p)
  }
  if sec.source_line != "" {
    _full("source", sec.id, {
      set text(size: 9pt, fill: colour("muted"))
      sec.source_line
    })
  }
})
