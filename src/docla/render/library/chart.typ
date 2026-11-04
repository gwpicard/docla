#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, chart-colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let chart(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let data = sec.at("data", default: (:))
  let categories = data.at("categories", default: ())
  let series = data.at("series", default: ())
  let kind = data.at("type", default: "")
  let plot-w = content-frame.w - 120pt
  let plot-h = 280pt
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("figure", sec.id, content-frame.w, content-frame.h, {
      el("figure", sec.id, {
        if kind != "bar" and kind != "column" {
          set text(..type-style("slides", "body"), fill: colour("ink"))
          [chart type not supported]
        } else {
          let maximum = calc.max(1, ..series.map(s => calc.max(0, ..s.values)))
          fit-box("chart-capacity", sec.id, content-frame.w, 320pt, {
            block(height: categories.len() * 40pt)
          })
          place(top + left, dx: 100pt, dy: 0pt, {
            el("chart-plot", sec.id, block(width: plot-w, height: plot-h))
          })
          for (i, category) in categories.enumerate() {
            for (j, s) in series.enumerate() {
              let value = s.values.at(i, default: 0)
              let count = calc.max(1, series.len())
              let slot = if kind == "bar" { plot-h / calc.max(1, categories.len()) } else { plot-w / calc.max(1, categories.len()) }
              let thickness = slot / count * 0.7
              let length = if kind == "bar" { plot-w * calc.max(0, value) / maximum } else { plot-h * calc.max(0, value) / maximum }
              let x = if kind == "bar" { 100pt } else { 100pt + i * slot + j * slot / count }
              let y = if kind == "bar" { i * slot + j * slot / count } else { plot-h - length }
              let w = if kind == "bar" { length } else { thickness }
              let h = if kind == "bar" { thickness } else { length }
              place(top + left, dx: x, dy: y, el("chart-mark", sec.id, rect(width: w, height: h, fill: chart-colour(j), stroke: none)))
              let label-x = if kind == "bar" { 0pt } else { x }
              let label-y = if kind == "bar" { y } else { plot-h + 2pt }
              place(top + left, dx: label-x, dy: label-y, {
                set text(..type-style("slides", "caption"), fill: colour("ink"))
                el("chart-label", sec.id, str(category))
              })
            }
          }
          if series.len() >= 2 {
            place(top + left, dy: 310pt, {
              set text(..type-style("slides", "caption"), fill: colour("ink"))
              el("chart-legend", sec.id, series.map(s => s.name).join("   "))
            })
          }
        }
        if source-line != "" {
          place(top + left, dy: 345pt, {
            set text(..type-style("slides", "caption"), fill: colour("muted"))
            el("figure-source", sec.id, source-line)
          })
        }
      })
    })
  })
})
