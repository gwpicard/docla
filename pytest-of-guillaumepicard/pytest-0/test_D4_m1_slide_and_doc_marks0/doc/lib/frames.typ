#import "/lib/marks.typ": fit-box
#import "/lib/theme.typ": type-style

#let title-frame = (x: 40pt, y: 40pt, w: 880pt, h: 60pt)
#let content-frame = (x: 40pt, y: 120pt, w: 880pt, h: 380pt)
#let full-frame = (x: 40pt, y: 40pt, w: 880pt, h: 460pt)

#let slide-title(sec) = place(
  top + left,
  dx: title-frame.x,
  dy: title-frame.y,
  fit-box("title", sec.id, title-frame.w, title-frame.h, {
    set text(..type-style("slides", "title"))
    sec.title
  }),
)
