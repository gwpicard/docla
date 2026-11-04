#import "theme.typ": colour

#let cite-keys(citations) = {
  if citations.len() > 0 {
    text(fill: colour("muted"), citations.map(cite => {
      let locator = cite.at("locator", default: none)
      "[" + cite.key + (if locator == none or locator == "" { "" } else { " " + locator }) + "]"
    }).join(" "))
  }
}
