#import "/lib/theme.typ": colour, page-setup
#import "/components/reader.typ": reader

#show: page-setup.with("slides")
#set text(fill: colour("ink"))

#let comp = json("/composition.json")
#let sec = comp.sections.at(0).props + comp.sections.at(0).content
#reader(sec)
