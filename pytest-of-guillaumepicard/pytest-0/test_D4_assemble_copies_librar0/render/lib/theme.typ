// Theme stub until theme tokens generate this file.
// Flow settings keep Typst's defaults.

#let tokens = (
  ink: "#1a1a1a",
  paper: "#ffffff",
  accent: "#2f5d8a",
  muted: "#6b6b6b",
)

#let colour(name) = {
  if name not in tokens {
    panic("unknown colour token: " + name)
  }
  rgb(tokens.at(name))
}

#let page-setup(format, body) = {
  if format == "slides" {
    set page(width: 960pt, height: 540pt, margin: 0pt)
    body
  } else if format == "doc" {
    set page(paper: "a4", margin: 20mm)
    body
  } else {
    panic("unknown page format: " + repr(format) + "; use \"slides\" or \"doc\"")
  }
}
