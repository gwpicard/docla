# Context

This file holds the project vocabulary: each thing has one word, used identically in code, UI and docs.

| Term | Meaning |
|---|---|
| **Project** | A folder: source material, one or more documents, their versions. |
| **Document** | One deliverable: a *working file* plus its builds. Format is `slides` or `doc`. |
| **Working file** | `<name>.md`. Front matter plus sections. The only editable state of a document. |
| **Section** | One outline line: one slide, or one component-sized block of a document page. Has a stable id. |
| **Intent** | What a section's content *is* (`key-numbers`, `comparison`, `quote`...). The author states intent; the chooser picks the component. |
| **Component** | Code that draws a section: a Typst function with a typed props schema and a capacity. |
| **Chooser** | Data table mapping intent plus content features to a component. |
| **Doctype** | A document type (`pitch-deck`, `report`...): outline, questions, checks, checklist. |
| **Theme** | The brand system for a project: tokens, components, rules, rubric, voice, exemplars. |
| **Token** | A named brand value (colour, type scale, spacing). |
| **Rule** | A named, testable requirement with severity, tier and remedy. |
| **Check** | The code or declarative spec that implements a rule. |
| **Finding** | One violation: rule, section, location, evidence, measured value. |
| **Fix** | A patch to a section that addresses a set of findings. |
| **Swatch** | A section rendered alone on its component's frame, for fast micro checks. |
| **Layout facts** | Machine-readable description of a rendered PDF: text runs, colours, boxes, plus semantic marks emitted by components. |
| **Look** | The pass that rasterises a build, runs all sensors and records the result. |
| **Critic** | The vision model call that judges screenshots against a closed rubric. |
| **Feedback** | A person's comment anchored to a section or region. |
| **Diagnosis** | The model's classification of why feedback arose. |
| **Learning** | A durable change to the theme produced from feedback or from repair history. |
| **Probation** | The period a new learning is advisory before it can block. |
| **Version** | An immutable build: outputs, build record, manifest, screenshots. |
