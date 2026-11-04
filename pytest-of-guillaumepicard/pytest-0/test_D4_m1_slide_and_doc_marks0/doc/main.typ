#import "/lib/theme.typ": colour, page-setup
#import "/components/body.typ": body
#import "/components/callout.typ": callout

#show: page-setup.with("doc")
#set text(fill: colour("ink"))

#let comp = json("/composition.json")
#let sec = comp.sections.at(0).props + comp.sections.at(0).content
#body(sec)
#let sec = comp.sections.at(1).props + comp.sections.at(1).content
#callout(sec)
