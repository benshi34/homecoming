// A stand-in for Apple's Speech framework. Tests compile the real hear.swift against it so no model is downloaded.
import AVFoundation
import Foundation

func event(_ value: String) {
    let url = URL(fileURLWithPath: ProcessInfo.processInfo.environment["HEAR_EVENTS"]!)
    if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
    let file = try! FileHandle(forWritingTo: url)
    file.seekToEndOfFile()
    file.write(Data((value + "\n").utf8))
    try! file.close()
}

public protocol SpeechModule {}

public struct SpeechTranscriber: SpeechModule {
    public enum TranscriptionOption {}
    public enum ReportingOption {}
    public enum AttributeOption { case transcriptionConfidence }
    let locale: Locale
    public init(locale: Locale, transcriptionOptions: [TranscriptionOption], reportingOptions: [ReportingOption],
                attributeOptions: [AttributeOption]) { self.locale = locale }
    public static func supportedLocale(equivalentTo locale: Locale) async -> Locale? { locale }
    public var results: Results { Results() }
}

public struct TextRun {
    public let range = 0..<1
    public let transcriptionConfidence: Double? = 0.9
}

public struct Text {
    public var characters: [Character] { Array("the ferry leaves at ten") }
    public var runs: [TextRun] { [TextRun()] }
    public subscript(range: Range<Int>) -> Text { self }
}

public struct Result {
    public var text: Text { Text() }
}

public struct Results {
    public func reduce<T>(_ initial: T, _ next: (T, Result) throws -> T) async rethrows -> T {
        try next(initial, Result())
    }
}

public enum AssetInventory {
    // As on a real Mac (macOS 26.4 and 27): an installed model's status is .supported too, not .installed.
    public enum Status { case installed, supported }
    public static func status(forModules modules: [any SpeechModule]) async -> Status { .supported }
    // nil when the model is on this Mac, as Apple's is; asking downloads nothing
    public static func assetInstallationRequest(supporting modules: [any SpeechModule]) async throws -> AssetInstallationRequest? {
        let locale = (modules[0] as! SpeechTranscriber).locale.identifier
        let installed = ProcessInfo.processInfo.environment["HEAR_INSTALLED"] ?? ""
        return installed.split(separator: ",").map(String.init).contains(locale) ? nil : AssetInstallationRequest(locale: locale)
    }
}

public struct AssetInstallationRequest {
    let locale: String
    public func downloadAndInstall() async throws { event("download:\(locale)") }
}

public struct SpeechAnalyzer {
    public init(modules: [any SpeechModule]) {}
    public func analyzeSequence(from file: AVAudioFile) async throws -> Int? { event("analyze"); return 1 }
    public func finalizeAndFinish(through last: Int) async throws {}
    public func cancelAndFinishNow() async {}
}
