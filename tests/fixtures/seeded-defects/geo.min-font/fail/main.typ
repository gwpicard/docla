// A slide whose only section sets its text at 12 pt, below the 18 pt minimum for slides.

#import "/lib/marks.typ": section
#import "/lib/theme.typ": colour, page-setup

#show: page-setup.with("slides")
#set text(fill: colour("ink"))

#pad(x: 80pt, y: 120pt, section("s1", {
  set text(size: 12pt)
  [Inspection intervals were set in 2019 and never revised.]
}))
