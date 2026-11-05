#import "/lib/marks.typ": fit-box
#import "/lib/theme.typ": type-style, pages

#let margins = pages.at("slides", default: (:)).at("margin", default: (top: 40pt, right: 40pt, bottom: 40pt, left: 40pt))
#let width = 960pt - margins.left - margins.right
#let height = 540pt - margins.top - margins.bottom
#let title-frame = (x: margins.left, y: margins.top, w: width, h: 60pt)
#let content-frame = (x: margins.left, y: margins.top + 80pt, w: width, h: height - 80pt)
#let full-frame = (x: margins.left, y: margins.top, w: width, h: height)

#let slide-title(sec) = place(
  top + left,
  dx: title-frame.x,
  dy: title-frame.y + type-style("slides", "title").size / 20,
  fit-box("title", sec.id, title-frame.w, title-frame.h, {
    set text(..type-style("slides", "title"))
    sec.title
  }),
)
