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
        set text(..type-style("slides", "caption"), fill: colour("ink"))
        if kind != "bar" and kind != "column" {
          [chart type not supported]
        } else {
          let maximum = calc.max(1, ..series.map(s => calc.max(0, ..s.values)))
          el("chart-plot", sec.id, {
            if kind == "bar" {
              let rows = ()
              for (i, category) in categories.enumerate() {
                for (j, s) in series.enumerate() {
                  let value = s.values.at(i, default: 0)
                  rows.push(block(height: 18pt, grid(columns: (120pt, plot-w), align: horizon, gutter: 0pt,
                    el("chart-label", sec.id, str(category)),
                    el("chart-mark", sec.id, rect(width: plot-w * calc.max(0, value) / maximum, height: 12pt, fill: chart-colour(j), stroke: none)),
                  )))
                }
              }
              stack(dir: ttb, spacing: 0pt, ..rows)
            } else {
              block(width: content-frame.w, height: plot-h + 50pt, {
                for (i, category) in categories.enumerate() {
                  for (j, s) in series.enumerate() {
                    let slot = plot-w / calc.max(1, categories.len())
                    let count = calc.max(1, series.len())
                    let length = plot-h * calc.max(0, s.values.at(i, default: 0)) / maximum
                    let x = 100pt + i * slot + j * slot / count
                    place(top + left, dx: x, dy: plot-h - length, el("chart-mark", sec.id, rect(width: slot / count * 0.7, height: length, fill: chart-colour(j), stroke: none)))
                    place(top + left, dx: x, dy: plot-h + 2pt, el("chart-label", sec.id, rotate(90deg, reflow: true, str(category))))
                  }
                }
              })
            }
          })
          if series.len() >= 2 {
            el("chart-legend", sec.id, series.map(s => s.name).join("   "))
          }
        }
        if source-line != "" {
          el("figure-source", sec.id, text(fill: colour("muted"), source-line))
        }
      })
    })
  })
})
