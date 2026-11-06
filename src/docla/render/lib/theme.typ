// Theme stub until theme tokens generate this file.
// Flow settings keep Typst's defaults.

#let tokens = (
  ink: "#1a1a1a",
  paper: "#ffffff",
  accent: "#2f5d8a",
  muted: "#6b6b6b",
)

#let pages = (slides: (margin: (top: 40pt, right: 40pt, bottom: 40pt, left: 40pt)))

#let type-style(format, role) = {
  if format == "slides" {
    if role == "figure" { (size: 40pt, weight: "bold") }
    else if role == "title" { (size: 32pt, weight: "bold") }
    else { (size: 20pt) }
  } else if role == "h1" { (size: 16pt, weight: "bold") }
  else if role == "caption" { (size: 9pt) }
  else { (size: 11pt) }
}

#let space(n) = n * 2pt

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
