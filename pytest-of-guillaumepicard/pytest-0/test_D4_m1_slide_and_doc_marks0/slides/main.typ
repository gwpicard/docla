#import "/lib/theme.typ": colour, page-setup
#import "/components/statement.typ": statement
#import "/components/bullets.typ": bullets

#show: page-setup.with("slides")
#set text(fill: colour("ink"))

#let comp = json("/composition.json")
#let sec = comp.sections.at(0).props + comp.sections.at(0).content
#statement(sec)
#pagebreak()
#let sec = comp.sections.at(1).props + comp.sections.at(1).content
#bullets(sec)
