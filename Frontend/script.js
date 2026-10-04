async function analyzeMeeting() {

    const fileInput = document.getElementById("meetingFile");
    const message = document.getElementById("message");

    if (!fileInput) {
        console.error("meetingFile input not found");
        return;
    }

    if (!message) {
        console.error("message element not found");
        return;
    }

    const file = fileInput.files[0];

    if (!file) {
        message.innerHTML = `
            <div class="error-box">
                ⚠️ Please upload a meeting audio file first.
            </div>
        `;
        return;
    }

    message.innerHTML = `
        <div class="loading-box">
            <h2>🤖 AI is analyzing your meeting...</h2>
            <p>Please wait while Meet2ActionAI processes the audio.</p>
        </div>
    `;

    try {

        const formData = new FormData();
        formData.append("file", file);

        console.log("Sending file to backend:", file.name);

        const response = await fetch(
            "https://meet2actionai.onrender.com/analyze",
            {
                method: "POST",
                body: formData
            }
        );

        console.log("Backend response status:", response.status);

        const result = await response.json();

        console.log("Backend result:", result);

        if (!response.ok) {
            throw new Error(
                result.error || "Meeting analysis failed"
            );
        }

        let actionItems = "";

        if (
            result.tasks &&
            Array.isArray(result.tasks) &&
            result.tasks.length > 0
        ) {

            result.tasks.forEach((task, index) => {

                const priority =
                    task.priority || "Low";

                const priorityClass =
                    priority.toLowerCase();

                actionItems += `
                    <div class="action-card">

                        <div class="action-number">
                            ${index + 1}
                        </div>

                        <div class="action-content">

                            <div class="action-row">
                                <span class="label">
                                    👤 Person
                                </span>

                                <strong>
                                    ${task.person || "Not identified"}
                                </strong>
                            </div>

                            <div class="action-row">
                                <span class="label">
                                    ✅ Task
                                </span>

                                <strong>
                                    ${task.task || "Not identified"}
                                </strong>
                            </div>

                            <div class="action-row">
                                <span class="label">
                                    📅 Deadline
                                </span>

                                <strong>
                                    ${task.deadline || "Not specified"}
                                </strong>
                            </div>

                            <div class="action-row">
                                <span class="label">
                                    🔥 Priority
                                </span>

                                <span class="priority ${priorityClass}">
                                    ${priority}
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

                    <div class="success-icon">
                        ✓
                    </div>

                    <div>
                        <h2>
                            Meeting Analyzed Successfully
                        </h2>

                        <p>
                            Meet2ActionAI has processed your meeting.
                        </p>
                    </div>

                </div>


                <section class="result-section">

                    <h3>
                        📝 Meeting Transcript
                    </h3>

                    <div class="transcript-box">
                        ${
                            result.result ||
                            "No speech detected."
                        }
                    </div>

                </section>


                <section class="result-section">

                    <div class="section-title">

                        <h3>
                            📋 Action Items
                        </h3>

                        <span class="task-count">
                            ${
                                result.tasks
                                    ? result.tasks.length
                                    : 0
                            } Tasks
                        </span>

                    </div>

                    <div class="action-list">
                        ${actionItems}
                    </div>

                </section>

            </div>
        `;

    } catch (error) {

        console.error(
            "Meet2ActionAI Error:",
            error
        );

        message.innerHTML = `
            <div class="error-box">

                ❌ <strong>
                    Analysis failed
                </strong>

                <p>
                    ${error.message}
                </p>

                <small>
                    Please check your internet connection
                    and try again.
                </small>

            </div>
        `;
    }
}