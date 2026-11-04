// Body section: a title and paragraphs that flow across pages.

#import "/lib/marks.typ": section, el-full-width
#import "/lib/theme.typ": colour

#let body(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  el-full-width("heading", sec.id, {
    set text(size: 16pt, weight: "bold")
    sec.title
  })
  set text(size: 11pt)
  for p in sec.paragraphs {
    par(p)
  }
  if sec.source_line != "" {
    el-full-width("source", sec.id, {
      set text(size: 9pt, fill: colour("muted"))
      sec.source_line
    })
  }
})
