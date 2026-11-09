#import "theme.typ": colour

#let cite-keys(citations, fill: none) = {
  if citations.len() > 0 {
    text(fill: if fill == none { colour("muted") } else { fill }, citations.map(cite => {
      let locator = cite.at("locator", default: none)
      "[" + cite.key + (if locator == none or locator == "" { "" } else { " " + locator }) + "]"
    }).join(" "))
  }
}
