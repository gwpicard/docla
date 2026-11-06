// Body section: a title and paragraphs that flow across pages.

#import "/lib/marks.typ": section, el-full-width
#import "/lib/theme.typ": colour, type-style

#let body(sec) = section(sec.id, {
  set text(fill: colour("ink"))
  el-full-width("heading", sec.id, {
    set text(..type-style("doc", "h1"))
    sec.title
  })
  set text(..type-style("doc", "body"))
  for p in sec.paragraphs {
    par(p)
  }
  if sec.source_line != "" {
    el-full-width("source", sec.id, {
      set text(..type-style("doc", "caption"), fill: colour("muted"))
      sec.source_line
    })
  }
})
