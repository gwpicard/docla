#import "/lib/marks.typ": section, el
#set page(width: 960pt, height: 540pt, margin: 0pt)
#section("s1", {
  place(top + left, dx: 160pt, dy: 100pt, el("chart-mark", "s1", rect(width: 380pt, height: 12pt)))
  place(top + left, dx: 40pt, dy: 152pt, el("chart-label", "s1", [North]))
})
