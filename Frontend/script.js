async function analyzeMeeting() {

    const fileInput = document.getElementById("meetingFile");
    const message = document.getElementById("message");
    const file = fileInput.files[0];

    if (!file) {
        message.innerHTML = "⚠️ Please upload a meeting file first.";
        return;
    }

    message.innerHTML = `
        <div class="loading-box">
            <h2>🤖 AI is analyzing your meeting...</h2>
            <p>Please wait while we process the audio.</p>
        </div>
    `;

    try {

        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch(
            "http://127.0.0.1:5001/analyze",
            {
                method: "POST",
                body: formData
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Analysis failed");
        }

        let actionItems = "";

        if (result.tasks && result.tasks.length > 0) {

            result.tasks.forEach((task, index) => {

                let priorityClass =
                    task.priority.toLowerCase();

                actionItems += `
                    <div class="action-card">

                        <div class="action-number">
                            ${index + 1}
                        </div>

                        <div class="action-content">

                            <div class="action-row">
                                <span class="label">👤 Person</span>
                                <strong>${task.person}</strong>
                            </div>

                            <div class="action-row">
                                <span class="label">✅ Task</span>
                                <strong>${task.task}</strong>
                            </div>

                            <div class="action-row">
                                <span class="label">📅 Deadline</span>
                                <strong>${task.deadline}</strong>
                            </div>

                            <div class="action-row">
                                <span class="label">🔥 Priority</span>
                                <span class="priority ${priorityClass}">
                                    ${task.priority}
                                </span>
                            </div>

                        </div>

                    </div>
                `;
            });

        } else {

            actionItems = `
                <div class="no-task">
                    ℹ️ No action items detected from this meeting.
                </div>
            `;
        }

        message.innerHTML = `

            <div class="meeting-result">

                <div class="success-header">
                    <div class="success-icon">✓</div>

                    <div>
                        <h2>Meeting Analyzed Successfully</h2>
                        <p>Meet2ActionAI has processed your meeting.</p>
                    </div>
                </div>


                <section class="result-section">

                    <h3>📝 Meeting Transcript</h3>

                    <div class="transcript-box">
                        ${result.result || "No speech detected."}
                    </div>

                </section>


                <section class="result-section">

                    <div class="section-title">
                        <h3>📋 Action Items</h3>
                        <span class="task-count">
                            ${result.tasks ? result.tasks.length : 0} Tasks
                        </span>
                    </div>

                    <div class="action-list">
                        ${actionItems}
                    </div>

                </section>

            </div>
        `;

    } catch (error) {

        console.error(error);

        message.innerHTML = `
            <div class="error-box">
                ❌ <strong>Analysis failed</strong>
                <p>${error.message}</p>
            </div>
        `;
    }
}