// What's said in audio files, heard on this Mac by Apple's own speech recognition (SpeechTranscriber, macOS 26 on):
// nothing leaves the Mac. connectors/transcribe.py compiles it once and runs it.
//
//     hear en-US,zh-CN < paths      one audio file a line in; one JSON line out for each:
//                                   {"path", "text", "locale", "confidence"} or {"path", "error"}
//
// Each file is heard in each language given, and the hearing Apple is surest of (mean confidence over what it heard)
// is kept. A language whose model isn't on the Mac is downloaded once, by the system, as Dictation's are.

import AVFoundation
import Foundation
import Speech

struct Heard: Encodable {
    let path: String
    var text: String?
    var locale: String?
    var confidence: Double?
    var error: String?
}

func hear(_ url: URL, _ locale: Locale) async throws -> (String, Double) {
    let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [],
                                        attributeOptions: [.transcriptionConfidence])
    if let install = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
        try await install.downloadAndInstall()
    }
    let analyzer = SpeechAnalyzer(modules: [transcriber])
    let file = try AVAudioFile(forReading: url)
    async let heard: (String, Double, Int) = transcriber.results.reduce(("", 0.0, 0)) { acc, result in
        var (text, sum, n) = acc
        for run in result.text.runs {
            let count = result.text[run.range].characters.count
            if let c = run.transcriptionConfidence {
                sum += c * Double(count)
                n += count
            }
        }
        text += String(result.text.characters)
        return (text, sum, n)
    }
    if let last = try await analyzer.analyzeSequence(from: file) {
        try await analyzer.finalizeAndFinish(through: last)
    } else {
        await analyzer.cancelAndFinishNow()
    }
    let (text, sum, n) = try await heard
    return (text.trimmingCharacters(in: .whitespacesAndNewlines), n > 0 ? sum / Double(n) : 0)
}

let asked = CommandLine.arguments.count > 1 ? CommandLine.arguments[1].split(separator: ",").map(String.init) : ["en-US"]
var locales: [Locale] = []
for id in asked {
    if let l = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: id)),
       !locales.contains(where: { $0.identifier == l.identifier }) {
        locales.append(l)
    }
}
let encoder = JSONEncoder()
while let line = readLine() {
    let path = line.trimmingCharacters(in: .whitespacesAndNewlines)
    if path.isEmpty { continue }
    var out = Heard(path: path)
    if locales.isEmpty {
        out.error = "none of these languages can be heard on this Mac: \(asked.joined(separator: ", "))"
    }
    for locale in locales {
        do {
            let (text, confidence) = try await hear(URL(fileURLWithPath: path), locale)
            // the surest hearing that heard something; nothing heard in any language is an empty text
            if out.text == nil || (!text.isEmpty && (out.text!.isEmpty || confidence > out.confidence!)) {
                out.text = text
                out.locale = locale.identifier
                out.confidence = confidence
            }
        } catch {
            if out.text == nil { out.error = "\(error)" }
        }
    }
    if out.text != nil { out.error = nil }
    if let data = try? encoder.encode(out), let s = String(data: data, encoding: .utf8) {
        print(s)
        fflush(stdout)
    }
}
