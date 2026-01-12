export class SSEManager {
    private eventSource: EventSource | null = null;
    private url: string;
    private onMessage: (event: MessageEvent) => void;
    private onError: (event: Event) => void;

    constructor(
        url: string,
        onMessage: (event: MessageEvent) => void,
        onError: (event: Event) => void
    ) {
        this.url = url;
        this.onMessage = onMessage;
        this.onError = onError;
    }

    connect() {
        this.eventSource = new EventSource(this.url);
        this.eventSource.onmessage = this.onMessage;
        this.eventSource.addEventListener('status', this.onMessage);
        this.eventSource.onerror = this.onError;
    }

    disconnect() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}
