"""Collection registry for the shared Firestore database.

The Python API shares Firestore with the Java ProcounsellorApp backend. To make
sure this service can never alter existing data, every collection is READ-ONLY
unless it is listed in ``WRITABLE_COLLECTIONS``.

Rules for adding a collection here:
  * It must be a NEW collection owned by this service.
  * It must not appear in ``JAVA_OWNED_COLLECTIONS`` (enforced by tests).
"""

from __future__ import annotations

# New collections this service owns and may write. Add feature collections here.
WRITABLE_COLLECTIONS: frozenset[str] = frozenset({
    # MBA prep (docs/mba-api.md)
    "mbaExams", "mbaPapers", "mbaQuestionSets", "mbaQuestions", "mbaTests", "mbaAttempts",
    "mbaProfiles", "mbaQuestionStats", "mbaStudyTasks", "mbaAiUsage",
    # MBA Phase D: programmes (cutoffs embedded) and student shortlists
    "mbaPrograms", "mbaShortlists",
    "mbaCounsellorRequests",  # MBA "talk to my counsellor" requests
    "mbaNotificationState",  # MBA in-app notification read state (userId -> lastSeenAt, dismissed)
    "mbaGdpiItems", "mbaGdpiSessions",  # MBA GDPI (WAT/GD/PI) content + mock sessions
    "mbaAttemptAnalyses", "mbaQuestionReports",  # MBA mock analyst cache + question issue reports
    "mbaLeaderboardPrefs", "mbaDailyResults",  # MBA opt-in daily leaderboard
    "mbaTestScoreStats",  # MBA per-test score histogram of first attempts (ProCounsel percentile)
    "mbaApplicationDocs",  # MBA application document metadata (files in Storage under mba/applications/)
    "mbaExamUpdates",  # MBA admin-posted exam updates (admit card, answer key, results...) with official source URL
    "mbaDoubts", "mbaGroupMembers", "mbaCommunityUsage",  # MBA doubt threads (+ group posts), study-group membership, post limits
    "mbaSupportTickets", "mbaEvents",  # MBA help-centre tickets + admin-managed doubt hours / webinars
    "mbaCoachChats",  # MBA AI section coaches: last turns per student per coach (+ cached plan explanation)
    "mbaSyllabusProgress",  # MBA syllabus: per student per subtopic completed mark, bookmark, private note
})

# Top-level collections used by the Java backend (snapshot taken 2026-11-11 from
# ProcounsellorApp). Python must treat these as read-only.
JAVA_OWNED_COLLECTIONS: frozenset[str] = frozenset({
    "admins", "appVersionComparision", "appointments", "banner", "bannerInteraction",
    "banners", "becomeCounsellorPoints", "blogs", "callHistory", "callHistoryProBuddy",
    "callHistoryUser", "chats", "clients", "colleges", "communityActivity",
    "communityAnswers", "communityComments", "communityQuestions", "communityReplies",
    "counsellorActivityLogs", "counsellorAppointments", "counsellorBusinessDetails",
    "counsellorChats", "counsellorCourseList", "counsellorCourseReviews", "counsellorCourses",
    "counsellorLiveSession", "counsellorOfflineTransactions", "counsellorReview",
    "counsellorTestGroupList", "counsellorTestGroupReview", "counsellorTransactions",
    "counsellors", "courseCoupons", "courseTypes", "courses", "dailyGames",
    "deletedCounsellors", "deletedProBuddy", "deletedUsers", "deleted_counsellors",
    "deleted_users", "earningsAndPayout", "enquiry", "eventDeadlines", "exams",
    "foreignStudent", "gameItems", "gameSessions", "gameSets", "games",
    "grandMockTestRegistrations", "leads", "listOfQuestions", "liveSessionRequestApproval",
    "manualSubscriptionRequest", "notesForCounsellorRelatedToUser", "optionFormRegistrations",
    "otpEmailService", "outOfOffice", "out_of_office", "pcsatRegistrations", "proBuddy",
    "proBuddyCallRequests", "proBuddyReview", "proBuddyTransactions", "processedPayouts",
    "publicApiCollege", "rankingBodies", "reviews", "reviews_proBuddy", "schoolStudents",
    "states", "subscriptions", "successStories", "testGroup", "testSeries",
    "userActivityLogs", "userAppointments", "userChats", "userCoursesDetails",
    "userFavouriteCounsellors", "userOfflineTransactions", "userProBuddyReview",
    "userReview", "userSubscribedCounsellors", "userTestAnswers", "userTestAttempts",
    "userTestGroupDetails", "userTransactions", "users", "withdrawalRequests", "youtubeTokens",
})
